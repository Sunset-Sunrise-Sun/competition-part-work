export type RuntimeMode = 'browser' | 'backend';
const query = new URLSearchParams(typeof location === 'undefined' ? '' : location.search);
export const runtimeMode: RuntimeMode = query.get('runtime') === 'backend' ? 'backend' : 'browser';
// Network fallback requires an explicit opt-in; offline is the default.
export const strictOffline = query.get('assets') !== 'online';
