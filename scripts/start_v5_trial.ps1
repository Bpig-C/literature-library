param([switch]$Stop)
throw 'Legacy fixed-root launcher is unavailable in a recovered release. Use app/scripts/restored_runtime.py check --root <absolute-restored-root>, then serve --root <root> --port <explicit-free-port>. No service was started or stopped.'
