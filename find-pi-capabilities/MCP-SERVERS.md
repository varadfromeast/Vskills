# MCP Server Search

Load this reference only for an MCP or external-integration gap. Prefer an MCP
server already exposed in the session; online discovery is unnecessary when it
fully covers the requirement.

1. Search the [Official MCP Registry](https://registry.modelcontextprotocol.io/)
   with the strongest missing runtime noun phrase. If the registry has no direct
   fit, try one shorter alternative and stop. Treat registry presence as
   provenance metadata, not an endorsement.

2. Use the registry metadata, then fetch each plausible finalist's repository
   once. Inspect the complete server configuration, distribution manifest, and
   relevant tool source locally. Confirm that the declared tools directly cover
   the gap and that the transport and distribution can be used from Pi.

3. Verify publisher identity, maintenance, version, authentication and secret
   handling, data destination, network/filesystem/process access, write or
   destructive tools, and overlap with active capabilities. Reject a server
   whose permissions or external data handling are disproportionate to the gap.

4. Return the canonical Pi-compatible install/configuration command only when it
   is stated by the verified source. Otherwise mark installation as unresolved;
   do not invent client configuration from generic MCP examples.
