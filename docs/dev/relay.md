# Pairing relay

`apps/relay` is a tiny Cloudflare Worker with one SQLite-backed Durable Object (`PairingRoom`). It forwards opaque, end-to-end encrypted binary frames between exactly two Bento devices for at most 10 minutes while they pair. It never stores, parses or logs frame contents, and it has no database bindings. The binding contract is [pairing-relay-contract.md](../../orchestration/api/pairing-relay-contract.md).

The relay is optional infrastructure: when `BENTO_RELAY_URL` is not set or the relay is unreachable, Bento pairs devices through the user’s own Telegram Sync channel instead: the new device must sign in to Telegram first, and its name and platform are briefly visible in that channel.

## What the relay sees

- Both devices’ IP addresses (Cloudflare needs them to deliver the connection). Rate limiting uses a hash of the IP, never the raw value.
- The 4-character nameplate (first group of the pairing code), timing, and frame counts and sizes.
- Never the remaining 8 characters (the SPAKE2 password) or any plaintext: frames are AES-256-GCM encrypted with keys only the two devices derive.

Keep it that way: application logs contain only event names, room age, frame counts and error codes. Before enabling Cloudflare Workers Logs or other observability for this Worker, check what Cloudflare captures for each invocation (for example request headers), because the [privacy policy](../legal/en/privacy.md) promises relay logs without IP addresses and needs a retention period.

## Deploy

Prerequisites: a Cloudflare account (the Workers Free plan supports SQLite-backed Durable Objects) and Node 22 or later.

```sh
npm --prefix apps/relay ci
npm --prefix apps/relay test              # vitest-pool-workers suite, runs locally
npm --prefix apps/relay exec -- wrangler login
npm --prefix apps/relay run deploy
```

The deploy prints the Worker URL, for example `https://bento-relay.<account>.workers.dev`. Check it:

```sh
curl https://bento-relay.<account>.workers.dev/v1/health
# {"ok":true,"version":"…"}
```

`wrangler.jsonc` in `apps/relay` pins the compatibility date and declares the `PAIRING_ROOM` Durable Object binding, its `new_sqlite_classes` migration and the rate-limit binding; deploying applies them.

A custom domain (for example `relay.example.com`) is optional; add it to the Worker in the Cloudflare dashboard (Workers › your Worker › Domains & Routes) and use it in the URL below.

## Configure Bento builds

Bento connects with WebSockets, so the configured value uses the `wss://` scheme, with no path and no trailing slash:

```sh
gh variable set BENTO_RELAY_URL --body "wss://bento-relay.<account>.workers.dev"
```

It is not a secret (it ships inside every build), so a repository **variable** is enough. The desktop release workflow writes it into `resources/build-config.json`; headless and development runs read the `BENTO_RELAY_URL` environment variable. It also appears in Ajustes › Avanzado › relay.

## Local development

```sh
npm --prefix apps/relay run dev    # wrangler dev, by default on http://127.0.0.1:8787
```

Point local Bento instances at it with `BENTO_RELAY_URL=ws://127.0.0.1:8787` (plain `ws://` is for loopback development only). See [Multi-device development](multi-device.md).

## Operating it

- Rooms expire 10 minutes after the host connects; nothing persists after the Durable Object alarm.
- Limits: 64 KiB per frame, 128 frames per side, 20 room connections per minute per client IP.
- Redeploying is safe at any time; in-flight pairings fail and users simply create a new code.
- To retire the relay, remove `BENTO_RELAY_URL` from builds; new builds fall back to Telegram-channel pairing.
