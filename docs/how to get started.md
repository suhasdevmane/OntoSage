# 1. Drop in the TTL
cp /path/to/newbuilding.ttl input/bldg2.ttl

# 2. Create building config
cp config/buildings/bldg1.yaml config/buildings/bldg2.yaml
# edit: id, name, namespace, prefix, abox_file, db.host, db.database

# 3. Set building identity + DB secrets in .env
echo "BUILDING_ID=bldg2" >> .env
echo "DB_HOST=192.168.1.10" >> .env

# 4. Start everything
docker compose up -d
# bootstrap runs, orchestrator waits, then system is live

# When you're ready to try a new building later, the operator workflow will be:

### 1. cp new_building.ttl input/
### 2. cp config/buildings/bldg2.yaml config/buildings/bldg3.yaml # → edit with the new building's namespace and DB creds
### 3. Set BUILDING_ID=bldg3 in .env
### 4. docker compose up — bootstrap handles the rest automatically