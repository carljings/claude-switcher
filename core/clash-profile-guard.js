// claude-switcher-final-guard-v1; rendered by clash-profile-guard.py
function main(config) {
  const group = __PROXY_GROUP_JSON__;
  if (!(config['proxy-groups'] || []).some(g => g.name === group)) {
    throw new Error('Required fixed-exit group is missing');
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
