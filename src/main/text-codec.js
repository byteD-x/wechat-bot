const iconv = require('iconv-lite');

function looksLikeUtf16Text(buffer) {
    if (!Buffer.isBuffer(buffer) || buffer.length < 4) {
        return false;
    }
    if (
        buffer.subarray(0, 2).equals(Buffer.from([0xff, 0xfe]))
        || buffer.subarray(0, 2).equals(Buffer.from([0xfe, 0xff]))
    ) {
        return true;
    }

    const sample = buffer.subarray(0, Math.min(buffer.length, 4096));
    let evenZeros = 0;
    let oddZeros = 0;
    let evenCount = 0;
    let oddCount = 0;
    for (let index = 0; index < sample.length; index += 1) {
        if ((index % 2) === 0) {
            evenCount += 1;
            if (sample[index] === 0) evenZeros += 1;
        } else {
            oddCount += 1;
            if (sample[index] === 0) oddZeros += 1;
        }
    }
    if (!evenCount || !oddCount) {
        return false;
    }
    const evenRatio = evenZeros / evenCount;
    const oddRatio = oddZeros / oddCount;
    return Math.max(evenRatio, oddRatio) >= 0.3 && Math.min(evenRatio, oddRatio) <= 0.05;
}

function decodeBufferText(value) {
    const buffer = Buffer.isBuffer(value) ? value : Buffer.from(value || '');
    if (!buffer.length) {
        return '';
    }

    try {
        const utf8 = iconv.decode(buffer, 'utf-8');
        if (!utf8.includes('\ufffd')) {
            return utf8;
        }
    } catch (_) {}

    const fallbackEncodings = looksLikeUtf16Text(buffer)
        ? ['utf-16le', 'utf-16be', 'gb18030', 'cp936']
        : ['gb18030', 'cp936', 'utf-16le', 'utf-16be'];

    for (const encoding of fallbackEncodings) {
        try {
            const decoded = iconv.decode(buffer, encoding);
            if (decoded && !decoded.includes('\ufffd')) {
                return decoded;
            }
        } catch (_) {}
    }

    try {
        return buffer.toString('utf8');
    } catch (_) {
        return String(value || '');
    }
}

module.exports = {
    decodeBufferText,
};
