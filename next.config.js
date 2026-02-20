/** @type {import('next').NextConfig} */
module.exports = {
  compiler: {
    removeConsole: { exclude: ['error'] },
  },
};