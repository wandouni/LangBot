# Debug LangBot Frontend

Please refer to the [Development Guide](https://langbot.app/docs/en/develop/dev-config) for more information.

## Tests

Run the frontend smoke tests without a backend process:

```bash
pnpm test:e2e
```

The Playwright suite starts Vite and mocks the LangBot backend and Space APIs.

Two specs run against a real isolated backend and SDK Plugin Runtime instead:
`runner-real-runtime.spec.ts` and `wizard-real-stack.spec.ts`. They use
`vite preview` (run `pnpm build` first) and are launched by the pytest modules
`tests/e2e/test_runner_plugin_runtime.py` and
`tests/e2e/test_wizard_real_stack.py`; they skip when run through `pnpm test:e2e`.
