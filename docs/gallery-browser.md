# Browser prerequisites for gallery capture

Use an ordinary unprivileged Linux host account with an installed Chrome or
Chromium browser and a matching ChromeDriver. The browser is a qualification
prerequisite, separate from the target SDK. Install Selenium, display utilities
and fonts through the host distribution; do not rebuild an SDK to obtain a
browser. The [screenshot workflow](screenshots.md) retains the exact application
and SDK identities independently.

Run the bounded [preflight helper](../tools/gallery_browser.py) before SDK
installation and application builds:

```sh
python3 -B tools/gallery_browser.py --output build/browser-preflight
```

The output directory must be new. The helper supervises all browser descendants,
limits runtime to 90 seconds, passes only local path, home, temporary-directory,
locale and display settings to its children, and retains `preflight.json`, `console.log`, the
ChromeDriver log, a browser profile and a small rendered PNG. A failed or uncertain
probe preserves its evidence; it must stop the dependent build. Keep these files
in private diagnostic storage rather than adding the profile to a public gallery.
Passing this probe establishes the declared browser prerequisite only. GitHub
authentication, Actions identity credentials, loader overrides and browser flag
overrides are excluded from the child environment.

The helper selects an explicitly installed `google-chrome`, `google-chrome-stable`
or `chromium` and `chromedriver`. It checks matching major versions and never
invokes a download manager as a normal acquisition path. `chrome_options(profile)`
requires a fresh profile; `chrome_service(log_path)` reserves a new log and passes
the driver's `--log-path` option. This works with Bookworm's Selenium 4.8.3 and
current Selenium; the older implementation silently ignores `log_output`.
[Bookworm package](https://packages.debian.org/bookworm/python3-selenium),
[upstream Service source](https://github.com/SeleniumHQ/selenium/blob/selenium-4.8.0/py/selenium/webdriver/chrome/service.py).

`sandbox_status(browser)` visits Chromium's own `chrome://sandbox` page. Both the
older separate namespace/setuid rows and the newer first-layer row are supported.
It requires an active first layer, PID and network namespaces, the seccomp filter,
and Chromium's positive overall evaluation. This follows Chromium's
[Linux sandbox evaluation](https://chromium.googlesource.com/chromium/src/+/main/chrome/browser/ui/webui/sandbox/sandbox_internals_ui.cc).
Unknown, missing, conflicting or disabled fields fail. The exact rows and optional
thread synchronization status remain in the receipt. Actual browser arguments
that disable sandbox components are rejected. A second check renders text and a
canvas in a fixed viewport and captures its real pixels after fonts finish loading.

Ubuntu 24.04 restricts unprivileged user namespaces through AppArmor. Use the
host's maintained browser installation and corresponding policy; copying a
browser binary to another path may lose that permission. The probe records the
current AppArmor label and relevant read-only kernel settings, and tests the
browser's resulting protection instead of inferring it from a package name.
[Ubuntu restriction guidance](https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces).
An AppArmor denial or unavailable namespace service is a failed host prerequisite.
Do not work around it by disabling Chromium's sandbox, changing a host-wide kernel
setting, granting extra administrative capabilities or disabling AppArmor.

The gallery runs its browser directly on the ordinary host. It does not require a
custom Docker policy. A container that cannot provide the same verified sandbox
is unsupported for this capture path. Fixture tests in
[test_gallery_browser.py](../tests/test_gallery_browser.py) cover old/current
diagnostics, disabled protections, incompatible drivers, real render responses,
logging compatibility and cleanup ordering. Actual host qualification still
requires the preflight and all seven application captures on that host.
