// Combined root config: runs both backend (tests/) and frontend (__tests__/) suites.
// References sub-configs for each environment.
/** @type {import('jest').Config} */
export default {
  projects: [
    '<rootDir>/jest.config.backend.cjs',
    '<rootDir>/jest.config.frontend.cjs',
  ],
};
