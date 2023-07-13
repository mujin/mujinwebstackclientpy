# 0.7.0 (2023-07-13)

- Add a decorator to break large query into a few small queries.
- Update graph client generation algorithm and regenerate the graph client.


# 0.6.0 (2023-06-28)

- Support backup encrypted system information for debugging purpose.


# 0.5.0 (2023-04-18)

- Support HTTP over Unix domain socket via optional `unixEndpoint` argument.


# 0.4.1 (2023-03-13)

- Regenerate graph client for new module library APIs.


# 0.4.0 (2023-03-12)

- Add `GetSchema` API.
- Generate graph client for `ListModules` API.


# 0.3.0 (2023-02-15)

- Remove automatic query field generation for graphql api. These fields can be
  changed frequently causing the webstack client to be unusuable. Users of
  graph api now nees to explicitly specify fields and subfields they are
  interested in.


# 0.2.0 (2022-12-01)

- Regenerate graph client for sensorLInkName.


# 0.1.3 (2023-01-18)

- Update GraphQL client.


# 0.1.2 (2023-01-13)

- Bugfix: Require `scenepk` argument in `GetSceneSensorMapping` and `SetSceneSensorMapping`


# 0.1.1 (2023-01-11)

- Update GraphQL client.


# 0.1.0 (2022-11-17)

- Port from mujincontrollerclientpy.

