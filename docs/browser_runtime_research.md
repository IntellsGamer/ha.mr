# Browser Runtime Research for Exact V26 Compatibility

## Sources

1. [Pyodide quickstart](https://pyodide.org/en/stable/usage/quickstart.html)
2. [Pyodide JavaScript API](https://pyodide.org/en/stable/usage/api/js-api.html)
3. [Pyodide deployment guidance](https://pyodide.org/en/0.26.3/usage/downloading-and-deploying.html)
4. [Pyodide service-worker guidance](https://pyodide.org/en/latest/usage/service-worker.html)

## Findings

Pyodide provides a CPython runtime compiled to WebAssembly and exposes `loadPyodide()` for browser initialization. JavaScript can execute Python through `runPython()` and retrieve callable functions from the Python global namespace. Pure-Python project files can be written into the runtime filesystem before importing them, allowing ha.mr to run the same codec modules rather than a divergent rewrite.[1] [2]

A specific release can be self-hosted from static files. The relevant runtime includes the JavaScript loader, WebAssembly binary, standard-library archive, and lock file; serving the runtime from immutable versioned URLs permits normal browser caching.[3] The core loader permits a custom `indexURL`, so ha.mr can point client initialization at its own static runtime directory rather than requiring an external CDN.[2]

A service worker can cache immutable runtime and codec assets, but service workers require HTTPS or localhost and have module-import restrictions. Client-side loader progress should therefore come from explicitly fetched runtime and codec assets, while ordinary Cache Storage caching remains the baseline for all supporting deployments.[4]

## Architecture decision

Exact V26 parity takes priority over a hand-maintained JavaScript port. The initial browser codec will therefore execute the **same Python V26 modules** in a pinned, self-hosted CPython/WebAssembly runtime. This preserves every legacy decoder, frozen codebook, arithmetic frame, static DEFLATE behavior, and candidate-selection tie behavior. A future independently ported JavaScript implementation can be admitted only after a byte-for-byte differential conformance suite proves equivalence.

## References

[1] [Pyodide quickstart](https://pyodide.org/en/stable/usage/quickstart.html)

[2] [Pyodide JavaScript API](https://pyodide.org/en/stable/usage/api/js-api.html)

[3] [Pyodide deployment guidance](https://pyodide.org/en/0.26.3/usage/downloading-and-deploying.html)

[4] [Pyodide service-worker guidance](https://pyodide.org/en/latest/usage/service-worker.html)
