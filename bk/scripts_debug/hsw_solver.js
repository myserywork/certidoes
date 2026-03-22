/**
 * HSW (hCaptcha Solver Worker) Proof-of-Work solver.
 * Downloads and executes hCaptcha's HSW WASM to generate PoW token.
 *
 * Usage: node hsw_solver.js <jwt_req>
 * Output: PoW solution string on stdout
 */
const https = require('https');
const vm = require('vm');

const JWT_REQ = process.argv[2];
if (!JWT_REQ) {
    process.stderr.write('Usage: node hsw_solver.js <jwt_req>\n');
    process.exit(1);
}

function log(msg) { process.stderr.write(`[HSW] ${msg}\n`); }

// Decode JWT to get WASM path
function decodeJWT(token) {
    const parts = token.split('.');
    if (parts.length < 2) return {};
    const payload = Buffer.from(parts[1], 'base64').toString();
    return JSON.parse(payload);
}

function fetchURL(url) {
    return new Promise((resolve, reject) => {
        const doFetch = (u) => {
            https.get(u, (resp) => {
                if (resp.statusCode === 301 || resp.statusCode === 302) {
                    doFetch(resp.headers.location);
                    return;
                }
                let data = '';
                resp.on('data', chunk => data += chunk);
                resp.on('end', () => resolve(data));
            }).on('error', reject);
        };
        doFetch(url);
    });
}

(async () => {
    try {
        const payload = decodeJWT(JWT_REQ);
        log(`JWT payload: f=${payload.f}, s=${payload.s}, t=${payload.t}, n=${payload.n}, c=${payload.c}`);

        const wasmPath = payload.l;
        if (!wasmPath) {
            log('No WASM path in JWT');
            process.exit(1);
        }

        const wasmUrl = `https://newassets.hcaptcha.com${wasmPath}`;
        log(`Fetching HSW from: ${wasmUrl}`);

        const hswCode = await fetchURL(wasmUrl);
        log(`HSW code length: ${hswCode.length}`);

        // The HSW module exports a function that takes the JWT and returns a PoW solution
        // Create a sandboxed environment to run it
        const sandbox = {
            self: {},
            globalThis: {},
            global: {},
            window: {},
            console: { log: () => {}, error: () => {}, warn: () => {} },
            setTimeout: setTimeout,
            setInterval: setInterval,
            clearTimeout: clearTimeout,
            clearInterval: clearInterval,
            atob: (s) => Buffer.from(s, 'base64').toString('binary'),
            btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
            TextEncoder: TextEncoder,
            TextDecoder: TextDecoder,
            crypto: require('crypto').webcrypto,
            WebAssembly: WebAssembly,
            fetch: async (url) => {
                const data = await fetchURL(url);
                return {
                    ok: true,
                    status: 200,
                    arrayBuffer: async () => Buffer.from(data, 'binary'),
                    text: async () => data,
                    json: async () => JSON.parse(data),
                };
            },
            navigator: {
                userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
            },
            location: { href: 'https://newassets.hcaptcha.com' },
            document: { createElement: () => ({ getContext: () => null }) },
            URL: URL,
            Blob: class Blob {
                constructor(parts) { this._parts = parts; }
            },
            Response: class {
                constructor(body) { this.body = body; }
            },
            Request: class {
                constructor(url, opts) { this.url = url; this.opts = opts; }
            },
            performance: { now: () => Date.now() },
            Uint8Array: Uint8Array,
            Int32Array: Int32Array,
            Float64Array: Float64Array,
            ArrayBuffer: ArrayBuffer,
            SharedArrayBuffer: typeof SharedArrayBuffer !== 'undefined' ? SharedArrayBuffer : ArrayBuffer,
            Promise: Promise,
            Map: Map,
            Set: Set,
            Symbol: Symbol,
            Object: Object,
            Array: Array,
            JSON: JSON,
            Math: Math,
            Number: Number,
            String: String,
            Boolean: Boolean,
            Date: Date,
            Error: Error,
            TypeError: TypeError,
            RegExp: RegExp,
            parseInt: parseInt,
            parseFloat: parseFloat,
            isNaN: isNaN,
            isFinite: isFinite,
            undefined: undefined,
            NaN: NaN,
            Infinity: Infinity,
            null: null,
        };
        sandbox.self = sandbox;
        sandbox.globalThis = sandbox;
        sandbox.global = sandbox;
        sandbox.window = sandbox;

        // Execute the HSW code in sandbox
        const context = vm.createContext(sandbox);
        vm.runInContext(hswCode, context, { timeout: 30000 });

        // The HSW module should have set up a function on self/window
        // Try to find and call the hsw function
        let hswFn = sandbox.hsw || sandbox.self.hsw || sandbox.h;

        if (!hswFn) {
            // Look for exported functions
            const keys = Object.keys(sandbox.self).filter(k => typeof sandbox.self[k] === 'function');
            log(`Available functions: ${keys.join(', ')}`);

            // Try common export patterns
            for (const key of keys) {
                if (key !== 'fetch' && key !== 'atob' && key !== 'btoa') {
                    hswFn = sandbox.self[key];
                    log(`Trying function: ${key}`);
                    break;
                }
            }
        }

        if (!hswFn) {
            log('No HSW function found');
            // Check if it's a module pattern
            log(`Self keys: ${Object.keys(sandbox.self).filter(k => !['fetch','atob','btoa','console','setTimeout','setInterval','clearTimeout','clearInterval','navigator','location','document','crypto','WebAssembly','TextEncoder','TextDecoder','URL','performance','Uint8Array','Int32Array','Float64Array','ArrayBuffer','SharedArrayBuffer','Promise','Map','Set','Symbol','Object','Array','JSON','Math','Number','String','Boolean','Date','Error','TypeError','RegExp','parseInt','parseFloat','isNaN','isFinite','undefined','NaN','Infinity','Blob','Response','Request','self','globalThis','global','window','null'].includes(k)).join(', ')}`);
            process.exit(1);
        }

        log('Calling HSW function...');
        const result = await hswFn(JWT_REQ);
        log(`HSW result: ${typeof result}, length: ${result ? result.length : 0}`);

        if (result) {
            process.stdout.write(result);
            process.exit(0);
        } else {
            log('No result from HSW');
            process.exit(1);
        }

    } catch (e) {
        log(`Error: ${e.message}`);
        log(e.stack);
        process.exit(1);
    }
})();
