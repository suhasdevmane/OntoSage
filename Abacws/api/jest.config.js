module.exports = {
  testEnvironment: 'node',
  roots: ['<rootDir>/tests'],
  testMatch: ['**/?(*.)+(spec|test).[jt]s'],
  verbose: false,
  maxWorkers: 1,
  detectOpenHandles: true,
  forceExit: true,
  globalSetup: '<rootDir>/tests/jest.globalSetup.js',
  globalTeardown: '<rootDir>/tests/jest.globalTeardown.js'
};
