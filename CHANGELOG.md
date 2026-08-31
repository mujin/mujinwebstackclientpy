# Changelog

## 1.1.1 (2026-08-13)

- Removed a deadlock that occurred when re-subscribing after a subscription dropped. `_EnsureWebSocketConnection` waited for the WebSocket to open while holding the subscription lock, which the background thread needs in order to report the dropped subscription, so neither thread could make progress. Connection setup now happens outside the subscription lock and is bounded by the subscribe timeout.
- The event loop thread now runs as a daemon so that a stalled event loop cannot block interpreter shutdown, and `Destroy` no longer waits indefinitely for subscriptions to stop.
- A connect that does not finish within the timeout is now cancelled and its socket closed, instead of being left to complete in the background. Previously such a connect could publish a WebSocket that no listener was reading from, so every later subscribe attached to it and silently received nothing. `SubscribeGraphAPI` reports the failure as `ControllerGraphClientException`.

## 1.1.0 (2026-08-12)

- `CreateLogEntries` now accepts a payload that is already encoded as JSON `bytes` and sends those bytes
  as the request body unchanged. Callers that serialize an entry for their own reasons, such as validating
  it before upload, can pass the result through instead of encoding the same payload twice.

## 1.0.0 (2026-07-31)

- Use `msgspec` for all JSON encoding and decoding, with a `ujson` fallback for types `msgspec` cannot serialize natively (such as `numpy` scalars and arrays).
- Removed the `json` re-export from the `mujinwebstackclient` package. Import `msgspec` directly instead.

### Breaking changes

`msgspec` serializes several types differently from `ujson`, so request bodies containing any
of the following now go out on the wire in a different form. Callers that send these types
must check that the server side accepts the new encoding.

| Value | Previously (`ujson`) | Now (`msgspec`) |
| --- | --- | --- |
| `float('nan')`, `float('inf')`, `float('-inf')` | raised `OverflowError` | encoded as `null` |
| `datetime.datetime`, `datetime.date` | integer Unix timestamp, e.g. `1767323045` | RFC 3339 string, e.g. `"2026-01-02T03:04:05Z"` |
| `datetime.time`, `datetime.timedelta` | raised `OverflowError` | ISO 8601 string, e.g. `"01:02:03"`, `"PT90S"` |
| `bytes` | string of escaped code points, e.g. `"\u0000\u0001abc"` | base64 string, e.g. `"AAFhYmM="` |
| `bytearray` | array of integers, e.g. `[97,98,99]` | base64 string, e.g. `"YWJj"` |
| `uuid.UUID` | object of every attribute, e.g. `{"bytes":..., "hex":..., "int":1, ...}` | canonical string, e.g. `"00000000-0000-0000-0000-000000000001"` |
| `decimal.Decimal` | JSON number, e.g. `1.5` | string, e.g. `"1.5"` |
| `enum.Enum` | object, e.g. `{"name":"RED","value":"red"}` | the member value, e.g. `"red"` |
| `str` with non-ASCII characters | escaped code points, e.g. `"\u65e5\u672c"` | raw UTF-8 bytes, e.g. `"日本"` |

Both forms are valid JSON, but `Content-Type: application/json` carries no charset, so servers
must decode the body as UTF-8 (the RFC 8259 default).

The non-finite floats are the most dangerous of these: a `NaN` that used to fail loudly at
encode time is now silently sent as `null`.

Types `msgspec` cannot serialize natively (arbitrary objects, `numpy` values) still go through
`ujson`, so the old encoding continues to apply to anything nested inside them — a `datetime`
held as an attribute of a plain object is still encoded as an integer timestamp.

On the decoding side, a JSON number too large for a 64-bit float (e.g. `1e400`) now raises
`APIServerError` instead of decoding to `float('inf')`.

## 0.9.37 (2026-07-07)

- Support backup and restore accounts (users, groups, roles, permissions).

## 0.9.36 (2026-07-03)

- Support backup and restore grafana monitoring resources.

## 0.9.35 (2026-06-26)

- Do not send request body on GET/HEAD requests.

## 0.9.34 (2026-05-12)

- Support backup calendar, logs and stats.

## 0.9.33 (2026-05-11)

- Removed a deadlock that occurred when unsubscribing from an active subscription while a background thread attempted to acquire a subscription lock already held by the main subscribing thread.

## 0.9.32 (2026-04-02)

- Re-generate graph api.

## 0.9.31 (2026-03-05)

- Support zip backup file archive format.

## 0.9.30 (2026-02-03)

- Support backup and restore schedules.

## 0.9.29 (2026-01-27)

- Remove the payload limit in controller subscription client.

## 0.9.28 (2026-01-19)

- Re-generate graph api.

## 0.9.27 (2026-01-14)

### Changes

- When a request response is 401 Unauthorized and a JSON Web Token was used for the request, clear the token and retry the request to fetch a new token via basic auth.

## 0.9.26 (2025-12-11)

### Changes

- Re-generate graph api.

## 0.9.25 (2025-12-05)

### Changes

- Re-generate graph api.

## 0.9.24 (2025-10-24)

### Bug fixes

- Add the missing `tlsSkipVerify` argument to `_CreateWebstackClient` in `mujin_webstackclientpy_downloaddata.py`.

## 0.9.23 (2025-10-24)

### Changes

- Handle TLS verification checks for the websocket connection based on the `tlsSkipVerify` option.
- Handle HTTP to HTTPS upgrades in websocket initialization.

## 0.9.22 (2025-10-23)

### Changes

- Add an option for skipping TLS verification.
- Allow redirects for HEAD and POST requests.

## 0.9.21 (2025-10-16)

### Changes

- Warn callers when they use the webstack client from different threads.

## 0.9.20 (2025-10-10)

### Changes

- Re-generate graph api.

## 0.9.19 (2025-09-25)

### Changes

- Add `backupSceneFormat` option to the backup API.

## 0.9.18 (2025-09-11)

### Changes

- Re-generate graph api.

## 0.9.17 (2025-08-29)

### Changes

- Add support for string default values in GraphQL APIs.
- Re-generate GraphQL APIs.

## 0.9.16 (2025-08-18)

### Changes

- Re-generate graph api.

## 0.9.15 (2025-08-04)

### Changes

- Re-generate graph api.

## 0.9.14 (2025-07-28)

### Changes

- Re-generate graph api.

## 0.9.13 (2025-07-24)

### Changes

- Re-generate graph api.

## 0.9.12 (2025-07-07)

### Changes

- Support an optional bodyId parameter when downloading environment.

## 0.9.11 (2025-07-04)

### Changes

- Re-generate graph client.
- Don't add trailing whitespace in generated client.
- Support default values parsed from the GraphQL schema.
- Support deprecation warnings parsed from the GraphQL schema.

## 0.9.10 (2025-06-26)

### Changes

- Raise WebStack client errors with a copy of the response content instead of the implicit iterator to allow caller to deserialize the content as many times as needed.

## 0.9.9 (2025-06-19)

### Changes

- Add startedAt and endedAt parameters to debug resource APIs.

## 0.9.8 (2025-06-17)

### Changes

- Allow choose queries/mutation/subscription explicitly.

## 0.9.7 (2025-06-05)

### Changes

- Generate GraphQL subscription methods based on WebStack GraphQL schema.

## 0.9.6 (2025-06-04)

### Changes

- Re-generate graph api.

## 0.9.5 (2025-05-27)

### Changes

- Initialize the event loop inside the dedicated thread to avoid clashing with other event loop in the main thread.

## 0.9.4 (2025-05-24)

### Changes

- Add optional parameter to download resolved environments through file download.

## 0.9.3 (2025-05-13)

### Changes

- Regenerate the graph client.
- Rename "application" to "webapp".

## 0.9.2 (2025-04-04)

### Changes

- Regenerate the graph client.

## 0.9.1 (2025-04-04)

### Changes

- Fix typing annotation.

## 0.9.0 (2025-03-28)

### Changes

- Add support for GraphQL subscriptions.

## 0.8.7 (2025-03-27)

### Changes

- Remove suffixes from archive file correctly

## 0.8.6 (2025-02-06)

### Changes

- Regenerate the graph client.

## 0.8.5 (2024-12-23)

### Changes

- Regenerate the graph client.

## 0.8.4 (2024-12-06)

### Changes

- Login through json web token automatically when a token is available.

## 0.8.3 (2024-11-08)

### Changes

- Added options to backup/restore iodd

## 0.8.2 (2024-07-05)

### Changes

- Added downloadSizeLimit parameter to the DownloadDebugResource function.

## 0.8.1 (2024-07-04)

### Changes

- Regenerate the graph client.

## 0.8.0 (2024-06-21)

### Changes

- Support `GetWebStackState`.

## 0.7.11 (2024-06-14)

### Changes

- Allow customizing headers in `CallGraphAPI` calls.

## 0.7.10 (2024-04-11)

### Changes

- Remove `CreateCycleLogs`.

## 0.7.9 (2024-04-10)

### Changes

- Add `HeadConfig` API.

## 0.7.8 (2024-03-19)

### Changes

- Regenerate the graph client.

## 0.7.7 (2024-02-29)

### Changes

- Regenerate the graph client.

## 0.7.6 (2023-11-05)

### Changes

- Add a decorator to break large query into a few small queries.
- Update graph client generation algorithm and regenerate the graph client.
- Introduce iterator for large queries.

## 0.7.5 (2023-10-09)

### Changes

- Handle PrimaryKey as str on Python3

## 0.7.4 (2023-09-19)

### Changes

- Add `CreateLogEntries` API and update GraphQL client.
- Fix readme file references to the old repository.

## 0.7.3 (2023-09-02)

### Changes

- Support updating the author header after the client is initialized.

## 0.7.2 (2023-08-13)

### Changes

- Add DownloadSignalLog

## 0.7.1 (2023-07-27)

### Changes

- Handle new webstack semantic version format.

## 0.7.0 (2023-06-28)

### Changes

- Regenerate graph client for new module library APIs.
- Add streaming API to download blobs.
- Set the default pool size to 10 for `UnixSocketConnectionPool`.

## 0.6.1 (2023-06-28)

### Changes

- Print download directory when downloading scene files.

## 0.6.0 (2023-06-28)

### Changes

- Support backup encrypted system information for debugging purpose.

## 0.5.0 (2023-04-18)

### Changes

- Support HTTP over Unix domain socket via optional `unixEndpoint` argument.

## 0.4.1 (2023-03-13)

### Changes

- Regenerate graph client for new module library APIs.

## 0.4.0 (2023-03-12)

### Changes

- Add `GetSchema` API.
- Generate graph client for `ListModules` API.

## 0.3.0 (2023-02-15)

### Changes

- Remove automatic query field generation for graphql api. These fields can be
  changed frequently causing the webstack client to be unusable. Users of
  graph api now need to explicitly specify fields and subfields they are
  interested in.

## 0.2.0 (2023-02-15)

### Changes

- Regenerate graph client for sensorLinkName.

## 0.1.3 (2023-01-18)

### Changes

- Update GraphQL client.

## 0.1.2 (2023-01-13)

### Changes

- Bugfix: Require `scenepk` argument in `GetSceneSensorMapping` and `SetSceneSensorMapping`

## 0.1.1 (2023-01-11)

### Changes

- Update GraphQL client.

## 0.1.0 (2022-11-17)

### Changes

- Port from mujincontrollerclientpy.
