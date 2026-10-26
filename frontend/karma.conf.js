// Karma config: headless Chrome. Falls back to Playwright's bundled Chromium when CHROME_BIN is unset.
if (!process.env.CHROME_BIN) {
  try {
    process.env.CHROME_BIN = require('@playwright/test').chromium.executablePath();
  } catch {
    /* use the system Chrome */
  }
}

module.exports = function (config) {
  config.set({
    basePath: '',
    frameworks: ['jasmine', '@angular-devkit/build-angular'],
    plugins: [
      require('karma-jasmine'),
      require('karma-chrome-launcher'),
      require('karma-jasmine-html-reporter'),
      require('karma-coverage'),
      require('@angular-devkit/build-angular/plugins/karma'),
    ],
    client: { jasmine: { random: false }, clearContext: false },
    reporters: ['progress'],
    browsers: ['ChromeHeadlessCI'],
    customLaunchers: {
      ChromeHeadlessCI: { base: 'ChromeHeadless', flags: ['--no-sandbox', '--disable-dev-shm-usage'] },
    },
    restartOnFileChange: true,
  });
};
