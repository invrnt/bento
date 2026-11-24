# Bento for Android

Kotlin + Compose UI over the embedded Python backend (Chaquopy). Binding docs:
`orchestration/architecture/android-runtime.md`, `orchestration/api/android-endpoints.md`.

## Build

```sh
export JAVA_HOME=<JDK 17>                      # AGP 9.5 does not run on newer JDKs here
python-wheels/build_all.sh                     # once: Android cp313 wheels into python-wheels/dist
./gradlew :app:assembleDebug -PbentoBuildPython=$(uv python find 3.13)   # -PbentoAbis=arm64-v8a,x86_64 for both ABIs
./gradlew testDebugUnitTest ktlintCheck detekt lintDebug -PbentoBuildPython=…
./gradlew :app:connectedDebugAndroidTest :smoke:connectedCheck -PbentoBuildPython=…   # emulator
./gradlew :core:api:checkOpenApiDrift          # needs uv; :core:api:updateOpenApiSnapshot rewrites core/api/openapi.json
```

## Modules

| Module | What |
|---|---|
| `app` | Application (engine warm-up), `MainActivity`, `ShareActivity` shell, navigation, Hilt graph, manifest |
| `core/engine` | `BentoEngine` (holders, `StateFlow<EngineState>`), Chaquopy runtime, `EngineService`, host bridges |
| `core/api` | Generated DTOs + `BentoEndpoints`, loopback OkHttp client, errors, events, Coil and Media3 |
| `core/data` | Repositories, Paging sources, optimistic mutations with undo, UI cache |
| `core/background` | WorkManager workers, UIDT job / dataSync FGS, notifications |
| `core/testing` | Fakes: engine runtime, every bridge, `FakeApiTransport` |
| `smoke` | Separate-process tests: SIGKILL during upload, Macrobenchmark cold-start smoke |

## Adding a screen (feature agents)

1. Add a key to `app/.../navigation/Routes.kt` (`@Serializable data class X(...) : Route`).
2. Replace or add one line in `BentoNavGraph.kt`: `entry<Route.X> { key -> XScreen(onOpen = { navigator.navigate(Route.Y(it)) }) }`.
3. Get data from `core/data` repositories (Hilt-injected); never call HTTP from composables.

Network calls suspend until the engine is `Ready`; render `cachedFirstScreen()` first for instant start.
