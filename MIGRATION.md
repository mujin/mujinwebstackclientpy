# 0.1.0 (Migrating from mujincontrollerclientpy)

- The package `mujincontrollerclient` was split into `mujinwebstackclient` and `mujinplanningclient`. To migrate, determine which methods are used by your controllerclient instance, and convert to the correct class from either package (or use both).

Certain classes and packages have been renamed:

- mujincontrollerclient → EITHER mujinwebstackclient OR mujinplanningclient
- controllerclientbase → webstackclient
- controllerclientraw → controllerwebclientraw
- ControllerClientError → WebstackClientError
