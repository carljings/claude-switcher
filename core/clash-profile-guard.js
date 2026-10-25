// claude-switcher-final-guard-v2; rendered by clash-profile-guard.py
function main(config) {
  const group = __PROXY_GROUP_JSON__;
  const protectedListener = __PROTECTED_LISTENER_JSON__;
  if (!(config['proxy-groups'] || []).some(g => g.name === group)) {
    throw new Error('Required fixed-exit group is missing');
  }
  if (protectedListener) {
    if (!(config.proxies || []).some(p => p.name === protectedListener.proxy)) {
      throw new Error('Required concrete fixed-exit node is missing');
    }
    const listener = Object.assign({type: 'http', listen: '127.0.0.1'}, protectedListener);
    const listeners = config.listeners || [];
    if (!Array.isArray(listeners)) throw new Error('Invalid existing listeners');
    let found = false;
    for (const existing of listeners) {
      if (existing.name === listener.name || String(existing.port) === String(listener.port)) {
        if (found || Object.keys(existing).length !== Object.keys(listener).length ||
            !Object.keys(listener).every(k => existing[k] === listener[k])) {
          throw new Error('Protected listener conflicts with existing configuration');
        }
        found = true;
      }
    }
    if (!found) config.listeners = listeners.concat([listener]);
  }
  const hosts = ['stun.miwifi.com', 'stun.chat.bilibili.com', 'stun.l.google.com', 'stun.cloudflare.com'];
  const domains = ['claude.ai', 'claude.com', 'anthropic.com', 'claudeusercontent.com',
    'challenges.cloudflare.com', 'datadoghq.com', 'segment.io', 'stripe.com', 'stripe.network',
    'stripecdn.com', 'intercom.io', 'intercomcdn.com', 'intercomassets.com'];
  const rules = [3478, 5349, 19302].map(p => 'AND,((NETWORK,udp),(DST-PORT,' + p + ')),REJECT')
    .concat(hosts.map(h => 'AND,((NETWORK,udp),(DOMAIN,' + h + ')),REJECT'))
    .concat(domains.map(d => 'DOMAIN-SUFFIX,' + d + ',' + group));
  config.rules = rules.concat((config.rules || []).filter(r => !rules.includes(r)));
  config.ipv6 = false;
  config.dns = Object.assign({}, config.dns || {}, {ipv6: false});
  return config;
}
