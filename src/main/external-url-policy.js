const net = require('node:net');

function normalizeHostname(hostname) {
    const raw = String(hostname || '').trim().toLowerCase();
    if (!raw) {
        return '';
    }
    if (raw.startsWith('[') && raw.endsWith(']')) {
        return raw.slice(1, -1);
    }
    return raw;
}

function validateExternalOpenUrl(url) {
    if (!url || typeof url !== 'string') {
        return { success: false, error: 'invalid_url' };
    }

    const rawUrl = String(url || '').trim();
    let parsed;
    try {
        parsed = new URL(rawUrl);
    } catch (_) {
        return { success: false, error: 'invalid_url' };
    }

    const protocol = String(parsed.protocol || '').toLowerCase();
    if (protocol === 'mailto:') {
        return { success: true, normalizedUrl: rawUrl };
    }
    if (!['http:', 'https:'].includes(protocol)) {
        return { success: false, error: 'blocked_protocol' };
    }
    if (parsed.username || parsed.password) {
        return { success: false, error: 'blocked_credentials' };
    }

    const hostname = normalizeHostname(parsed.hostname);
    const ipCandidate = hostname.includes('%') ? hostname.split('%')[0] : hostname;
    const ipVersion = net.isIP(ipCandidate);
    const isPrivateIPv4 = ipVersion === 4 && (
        ipCandidate.startsWith('10.')
        || ipCandidate.startsWith('127.')
        || ipCandidate.startsWith('169.254.')
        || ipCandidate.startsWith('192.168.')
        || /^172\.(1[6-9]|2\d|3[0-1])\./.test(ipCandidate)
    );
    const isPrivateIPv6 = ipVersion === 6 && (
        ipCandidate === '::1'
        || ipCandidate.startsWith('fc')
        || ipCandidate.startsWith('fd')
        || ipCandidate.startsWith('fe80:')
    );
    const isLocalHost = hostname === 'localhost' || hostname.endsWith('.localhost') || hostname.endsWith('.local');
    if (isLocalHost || isPrivateIPv4 || isPrivateIPv6) {
        return { success: false, error: 'blocked_private_host' };
    }

    return { success: true, normalizedUrl: rawUrl };
}

module.exports = {
    validateExternalOpenUrl,
};
