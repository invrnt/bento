"""Android adapters: ports implemented by calling the Kotlin host bridges (`architecture/android-runtime.md` §5).

Bridges are passed in as instances (`engine.configure(config)["bridges"]`), so nothing here looks Java classes up
by name and tests inject plain Python fakes with the same methods. Only this package and `interfaces/android`
may touch Chaquopy objects.
"""
