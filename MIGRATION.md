# 0.1.2 (Bugfix for migration)

The `scenepk` argument in `GetSceneSensorMapping` and `SetSceneSensorMapping` is required now.

# 0.1.0 (Migrating from mujincontrollerclientpy)

The package `mujincontrollerclient` was split into `mujinwebstackclient` and `mujinplanningclient`. To migrate, determine which methods are used by your controllerclient instance, and convert to the correct class from either package (or use both).

See [the migration instructions in `mujinplanningclientpy` for details](https://github.com/mujin/mujinplanningclientpy/blob/master/MIGRATION.md).

Some web-API-related classes and packages that have been renamed:

- mujincontrollerclient → EITHER mujinwebstackclient OR mujinplanningclient
- controllerclientbase → webstackclient
- controllerclientraw → controllerwebclientraw
- ControllerClientError → WebstackClientError
