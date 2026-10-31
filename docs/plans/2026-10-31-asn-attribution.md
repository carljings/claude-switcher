# Bind ASN attribution to the detected exit

## Problem and scope

`checkdetail` displays the Cloudflare-detected exit but obtains its ASN name from
IPinfo's self-IP endpoint. Under split routing those requests can leave through
different exits, so the displayed live ASN may describe another address. This
is a reproducible attribution defect, not evidence that a production request
leaked or an account was restricted.

Adapt only the explicit-IP lookup and response binding idea from upstream
`6600bf90db63b946286f3801f6b735aa01e7918c`.

## Minimal design

Validate the detected address as canonical IPv4 before requesting
`https://ipinfo.io/<ip>/json`. Accept only successful transport, HTTP 200, a JSON
object whose `ip` exactly matches, and a bounded, nonempty printable `org`.
Invalid input, malformed data, redirects, HTTP errors and mismatches produce
the existing unknown result, with no self-IP fallback.

Keep the existing ASN review information and name-only classification wording.
Do not add another provider or change routing, thresholds, language, timezone,
account handling, maintenance permissions or root components. Changing the
global route would exceed scope; adding classification providers would not fix
which address this lookup describes.

## Verification and delivery

1. Reproduce the wrong-address lookup with fake curl and an isolated HOME.
2. Exercise exact query URLs, response mismatch, invalid targets, HTTP/transport
   failures, malformed types and unsafe organization strings through the real
   `checkdetail` command; preserve all 14 output rows and review semantics.
3. Run applicable regressions, repository checksums and Swift model checks;
   prepare a signed universal candidate and verify its extracted contents.

Publish only the bounded source changes to the user's custom branch. The
installed application and user/root modules remain unchanged pending explicit
deployment authorization under the current AGENTS instructions. Private
migration packages and other devices are outside this delivery.
