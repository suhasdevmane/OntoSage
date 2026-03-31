"""
Authentication Manager for OntoSage 3.0
Handles user registration, login, and session management.

Phase 7.3 — Password Security Upgrade
  Passwords are now hashed with Argon2id (argon2-cffi) which is the
  2023 OWASP recommended algorithm, providing GPU/ASIC resistance via
  configurable memory and time cost parameters.

  Falls back to bcrypt (passlib[bcrypt]) if argon2-cffi is not installed.
  Falls back to SHA-256 (legacy) if neither is installed — NOT recommended
  for production; install argon2-cffi via requirements.txt.

  Hash format stored in DB:
    argon2id:<argon2-cffi encoded hash>
    bcrypt:<bcrypt encoded hash>
    sha256:<hex digest>   ← legacy, migrated on next login

  Transparent migration: when a user with a legacy SHA-256 hash logs in
  successfully, their hash is automatically rehashed with Argon2id and
  stored — no forced password reset required.
"""
import hashlib
import secrets
import json
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

from shared.utils import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Password hashing backend detection
# ─────────────────────────────────────────────────────────────────────────────

def _detect_hasher():
    """Return the best available password hashing backend."""
    try:
        from argon2 import PasswordHasher  # argon2-cffi
        return "argon2id"
    except ImportError:
        pass
    try:
        import bcrypt  # noqa
        return "bcrypt"
    except ImportError:
        pass
    logger.warning(
        "Neither argon2-cffi nor bcrypt is installed! "
        "Falling back to SHA-256 — install argon2-cffi for production."
    )
    return "sha256"


HASHER_BACKEND = _detect_hasher()
logger_pw = get_logger("auth.password")


class AuthManager:
    """Manages user authentication and sessions"""
    
    def __init__(self, redis_manager, postgres_manager=None):
        """
        Initialize authentication manager
        
        Args:
            redis_manager: RedisManager instance for session persistence
            postgres_manager: PostgresManager instance for user data persistence
        """
        self.redis = redis_manager
        self.postgres = postgres_manager
        self.session_ttl = 86400 * 7  # 7 days
        
    def _hash_password(self, password: str, salt: Optional[str] = None) -> Tuple[str, str]:
        """
        Hash a password using Argon2id (preferred) → bcrypt → SHA-256.

        Returns:
            Tuple of (hashed_password_with_prefix, salt)
            The salt is kept for backward-compat with SHA-256 legacy hashes;
            Argon2id/bcrypt embed the salt in the hash itself.
        """
        if not salt:
            salt = secrets.token_hex(16)

        if HASHER_BACKEND == "argon2id":
            from argon2 import PasswordHasher
            ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32)
            # Argon2id salt is generated internally; we combine with our salt
            hashed = ph.hash(f"{password}{salt}")
            return f"argon2id:{hashed}", salt

        if HASHER_BACKEND == "bcrypt":
            import bcrypt
            pw_bytes  = f"{password}{salt}".encode("utf-8")
            bc_salt   = bcrypt.gensalt(rounds=12)
            hashed    = bcrypt.hashpw(pw_bytes, bc_salt).decode("utf-8")
            return f"bcrypt:{hashed}", salt

        # SHA-256 legacy fallback
        salted = f"{password}{salt}".encode("utf-8")
        hashed = hashlib.sha256(salted).hexdigest()
        return hashed, salt  # no prefix for backward-compat

    def _verify_password(self, password: str, hashed: str, salt: str) -> bool:
        """
        Verify a password against its stored hash.
        Handles all three formats: argon2id:, bcrypt:, and legacy sha256.

        Returns:
            True if password is correct.
        """
        try:
            if hashed.startswith("argon2id:"):
                from argon2 import PasswordHasher
                from argon2.exceptions import VerifyMismatchError
                ph = PasswordHasher()
                try:
                    return ph.verify(hashed[len("argon2id:"):], f"{password}{salt}")
                except VerifyMismatchError:
                    return False

            if hashed.startswith("bcrypt:"):
                import bcrypt
                pw_bytes = f"{password}{salt}".encode("utf-8")
                stored   = hashed[len("bcrypt:"):].encode("utf-8")
                return bcrypt.checkpw(pw_bytes, stored)

            # Legacy SHA-256 (no prefix)
            salted   = f"{password}{salt}".encode("utf-8")
            computed = hashlib.sha256(salted).hexdigest()
            return computed == hashed

        except Exception as e:
            logger_pw.error(f"Password verification error: {e}")
            return False

    def _needs_rehash(self, hashed: str) -> bool:
        """
        Return True if the stored hash uses a legacy algorithm and should
        be transparently upgraded to Argon2id on next login.
        """
        if HASHER_BACKEND == "argon2id" and not hashed.startswith("argon2id:"):
            return True
        if HASHER_BACKEND == "bcrypt" and not hashed.startswith(("argon2id:", "bcrypt:")):
            return True
        return False
    
    async def register_user(
        self,
        username: str,
        password: str,
        email: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Register a new user
        
        Args:
            username: Unique username
            password: User password
            email: Optional email address
            metadata: Optional additional user data
            
        Returns:
            User registration result
            
        Raises:
            ValueError: If username already exists or invalid input
        """
        try:
            # Validate input
            if not username or len(username) < 3:
                raise ValueError("Username must be at least 3 characters")
            
            if not password or len(password) < 6:
                raise ValueError("Password must be at least 6 characters")
            
            # Check if user exists
            if self.postgres:
                user = await self.postgres.get_user(username)
                if user:
                    raise ValueError(f"Username '{username}' already exists")
            else:
                # Fallback to Redis if Postgres not available
                exists = await self.redis.client.exists(f"user:{username}")
                if exists:
                    raise ValueError(f"Username '{username}' already exists")
            
            # Hash password
            hashed_password, salt = self._hash_password(password)
            
            # Create user record
            user_data = {
                "username": username,
                "password_hash": hashed_password,
                "salt": salt,
                "email": email or "",
                "created_at": datetime.now().isoformat(),
                "last_login": "",
                "metadata": json.dumps(metadata or {})
            }
            
            if self.postgres:
                # Store in Postgres
                success = await self.postgres.create_user(
                    username, 
                    hashed_password, 
                    salt, 
                    email, 
                    metadata
                )
                if not success:
                    raise ValueError("Failed to create user in database")
            else:
                # Store in Redis (Legacy/Fallback)
                await self.redis.client.hset(
                    f"user:{username}",
                    mapping=user_data
                )
                # Add to users index
                await self.redis.client.sadd("users:all", username)
            
            logger.info(f"User registered: {username}")
            
            return {
                "success": True,
                "username": username,
                "message": "User registered successfully"
            }
            
        except ValueError as e:
            logger.warning(f"Registration failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"Registration error: {e}", exc_info=True)
            return {
                "success": False,
                "error": "Registration failed due to server error"
            }
    
    async def login_user(
        self,
        username: str,
        password: str
    ) -> Dict[str, Any]:
        """
        Authenticate user and create session
        
        Args:
            username: Username
            password: Password
            
        Returns:
            Login result with session token
        """
        try:
            # Get user data
            user_data = None
            if self.postgres:
                user_data = await self.postgres.get_user(username)
            
            # Fallback to Redis if not found in Postgres or Postgres not available
            if not user_data:
                user_data = await self.redis.client.hgetall(f"user:{username}")
            
            if not user_data:
                logger.warning(f"Login attempt for non-existent user: {username}")
                return {
                    "success": False,
                    "error": "Invalid username or password"
                }
            
            # Helper to get value from dict (handles bytes/string keys for Redis, string for Postgres)
            def get_value(data, key):
                if self.postgres and isinstance(data, dict) and not isinstance(list(data.keys())[0], bytes):
                    # Postgres returns dict with string keys
                    return data.get(key, "")
                
                # Redis returns bytes keys
                # Try bytes key first
                value = data.get(key.encode() if isinstance(key, str) else key)
                if value is None:
                    # Try string key
                    value = data.get(key if isinstance(key, str) else key.decode())
                if value and isinstance(value, bytes):
                    return value.decode('utf-8')
                return value or ""
            
            stored_hash = get_value(user_data, "password_hash")
            salt = get_value(user_data, "salt")
            
            logger.info(f"Login attempt - hash len: {len(stored_hash) if stored_hash else 0}, salt len: {len(salt) if salt else 0}")
            
            if not self._verify_password(password, stored_hash, salt):
                logger.warning(f"Invalid password for user: {username}")
                return {
                    "success": False,
                    "error": "Invalid username or password"
                }

            # Transparent hash migration: upgrade legacy SHA-256 → Argon2id
            if self._needs_rehash(stored_hash):
                logger_pw.info(f"Upgrading password hash for {username} to {HASHER_BACKEND}")
                new_hash, new_salt = self._hash_password(password)
                try:
                    if self.postgres:
                        await self.postgres.update_password(username, new_hash, new_salt)
                    else:
                        await self.redis.client.hset(f"user:{username}", mapping={
                            "password_hash": new_hash,
                            "salt":          new_salt,
                        })
                    logger_pw.info(f"Password hash upgraded for {username}")
                except Exception as mig_err:
                    logger_pw.warning(f"Hash migration failed (non-blocking): {mig_err}")
            
            # Create session token
            session_token = secrets.token_urlsafe(32)
            session_key = f"session:{session_token}"
            
            # Store session data
            session_data = {
                "username": username,
                "created_at": datetime.now().isoformat(),
                "last_activity": datetime.now().isoformat()
            }
            
            await self.redis.client.hset(
                session_key,
                mapping=session_data
            )
            
            # Set session expiration
            await self.redis.client.expire(session_key, self.session_ttl)
            
            # Update last login
            if self.postgres:
                await self.postgres.update_last_login(username)
            
            # Also update Redis for backward compatibility
            await self.redis.client.hset(
                f"user:{username}",
                "last_login",
                datetime.now().isoformat()
            )
            
            # Store session token for user (for logout all sessions)
            await self.redis.client.sadd(f"user_sessions:{username}", session_token)
            
            logger.info(f"User logged in: {username}")
            
            return {
                "success": True,
                "username": username,
                "session_token": session_token,
                "expires_in": self.session_ttl,
                "message": "Login successful"
            }
            
        except Exception as e:
            logger.error(f"Login error: {e}", exc_info=True)
            return {
                "success": False,
                "error": "Login failed due to server error"
            }
    
    async def validate_session(self, session_token: str) -> Optional[str]:
        """
        Validate session token and return username
        
        Args:
            session_token: Session token to validate
            
        Returns:
            Username if session is valid, None otherwise
        """
        try:
            session_data = await self.redis.client.hgetall(f"session:{session_token}")
            
            if not session_data:
                return None
            
            # Handle bytes/string keys
            username = session_data.get(b"username") or session_data.get("username")
            if isinstance(username, bytes):
                username = username.decode('utf-8')
            
            if not username:
                return None
            
            # Update last activity
            await self.redis.client.hset(
                f"session:{session_token}",
                "last_activity",
                datetime.now().isoformat()
            )
            
            # Refresh expiration
            await self.redis.client.expire(
                f"session:{session_token}",
                self.session_ttl
            )
            
            return username
            
        except Exception as e:
            logger.error(f"Session validation error: {e}")
            return None
    
    async def logout_user(self, session_token: str) -> Dict[str, Any]:
        """
        Logout user and invalidate session
        
        Args:
            session_token: Session token to invalidate
            
        Returns:
            Logout result
        """
        try:
            # Get session data
            session_data = await self.redis.client.hgetall(f"session:{session_token}")
            
            if not session_data:
                return {
                    "success": False,
                    "error": "Invalid session"
                }
            
            # Handle bytes/string keys
            username = session_data.get(b"username") or session_data.get("username")
            if isinstance(username, bytes):
                username = username.decode('utf-8')
            
            # Delete session
            await self.redis.client.delete(f"session:{session_token}")
            
            # Remove from user sessions
            await self.redis.client.srem(f"user_sessions:{username}", session_token)
            
            logger.info(f"User logged out: {username}")
            
            return {
                "success": True,
                "message": "Logged out successfully"
            }
            
        except Exception as e:
            logger.error(f"Logout error: {e}", exc_info=True)
            return {
                "success": False,
                "error": "Logout failed"
            }
    
    async def get_user_info(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Get user information (excluding password)
        
        Args:
            username: Username
            
        Returns:
            User info dict or None if not found
        """
        try:
            user_data = None
            if self.postgres:
                user_data = await self.postgres.get_user(username)
            
            if not user_data:
                user_data = await self.redis.client.hgetall(f"user:{username}")
            
            if not user_data:
                return None
            
            # Helper to get value from dict with bytes/string keys
            def get_val(key):
                if self.postgres and isinstance(user_data, dict) and not isinstance(list(user_data.keys())[0], bytes):
                    return user_data.get(key, "")
                
                val = user_data.get(key.encode() if isinstance(key, str) else key)
                if val is None:
                    val = user_data.get(key if isinstance(key, str) else key.decode())
                if val and isinstance(val, bytes):
                    return val.decode('utf-8')
                return val or ""
            
            # Decode and exclude sensitive data
            metadata_str = get_val("metadata")
            metadata = {}
            if metadata_str:
                try:
                    metadata = json.loads(metadata_str)
                except:
                    pass

            return {
                "username": get_val("username"),
                "email": get_val("email"),
                "created_at": str(get_val("created_at")),
                "last_login": str(get_val("last_login")),
                "metadata": metadata
            }
            
        except Exception as e:
            logger.error(f"Get user info error: {e}")
            return None
    
    async def update_user_metadata(
        self,
        username: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update user metadata
        
        Args:
            username: Username
            metadata: Metadata to update
            
        Returns:
            Update result
        """
        try:
            exists = await self.redis.client.exists(f"user:{username}")
            if not exists:
                return {
                    "success": False,
                    "error": "User not found"
                }
            
            await self.redis.client.hset(
                f"user:{username}",
                "metadata",
                json.dumps(metadata)
            )
            
            return {
                "success": True,
                "message": "Metadata updated"
            }
            
        except Exception as e:
            logger.error(f"Update metadata error: {e}")
            return {
                "success": False,
                "error": "Update failed"
            }
    
    async def list_all_users(self) -> list[str]:
        """
        Get list of all registered usernames
        
        Returns:
            List of usernames
        """
        try:
            usernames = await self.redis.client.smembers("users:all")
            return [u.decode('utf-8') for u in usernames]
        except Exception as e:
            logger.error(f"List users error: {e}")
            return []
    
    async def delete_user(self, username: str) -> Dict[str, Any]:
        """
        Delete user account and all associated data
        
        Args:
            username: Username to delete
            
        Returns:
            Deletion result
        """
        try:
            # Get all user sessions
            session_tokens = await self.redis.client.smembers(f"user_sessions:{username}")
            
            # Delete all sessions
            for token in session_tokens:
                token_str = token.decode('utf-8')
                await self.redis.client.delete(f"session:{token_str}")
            
            # Delete user data
            await self.redis.client.delete(f"user:{username}")
            await self.redis.client.delete(f"user_sessions:{username}")
            await self.redis.client.srem("users:all", username)
            
            # Delete user chat history
            # Find all conversation IDs for this user
            keys = await self.redis.client.keys(f"conversation:*")
            for key in keys:
                state_data = await self.redis.client.get(key)
                if state_data:
                    try:
                        state = json.loads(state_data)
                        if state.get("user_id") == username:
                            await self.redis.client.delete(key)
                    except:
                        pass
            
            logger.info(f"User deleted: {username}")
            
            return {
                "success": True,
                "message": f"User '{username}' deleted successfully"
            }
            
        except Exception as e:
            logger.error(f"Delete user error: {e}", exc_info=True)
            return {
                "success": False,
                "error": "Deletion failed"
            }
