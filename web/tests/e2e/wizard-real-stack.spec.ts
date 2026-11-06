import { expect, test } from '@playwright/test';

test.skip(
  !process.env.LANGBOT_WIZARD_API_URL,
  'Requires the isolated real backend started by tests/e2e/test_wizard_real_stack.py',
);

const LOCAL_AGENT_RUNNER_ID = 'plugin:langbot-team/LocalAgent/default';

test('real backend: login, quick-start wizard, create and save a Bot', async ({
  page,
  request,
}) => {
  const api = process.env.LANGBOT_WIZARD_API_URL!;
  const token = process.env.LANGBOT_WIZARD_TOKEN!;
  const adapterName = process.env.LANGBOT_WIZARD_ADAPTER_NAME!;
  const adapterLabel = process.env.LANGBOT_WIZARD_ADAPTER_LABEL!;
  const headers = { Authorization: `Bearer ${token}` };

  await page.addInitScript(() => {
    localStorage.setItem('langbot_language', 'en-US');
  });
  await page.goto('/login');
  await page.getByPlaceholder('Enter email address').fill('admin@langbot.test');
  await page.getByPlaceholder('Enter password').fill('admin');
  await page.getByRole('button', { name: 'Login with password' }).click();
  // A brand-new instance has wizard_status=none, so login lands on /wizard;
  // an already-initialized one lands on /home. Both prove the session is live.
  await expect(page).toHaveURL(/\/(home|wizard)/, { timeout: 60_000 });

  await page.goto('/wizard', { waitUntil: 'domcontentloaded' });
  await expect(
    page.getByText('Select a Platform', { exact: true }),
  ).toBeVisible({ timeout: 60_000 });

  await page.getByText(adapterLabel, { exact: true }).first().click();
  await page.getByRole('button', { name: 'Confirm, Create Bot' }).click();
  await expect(
    page.getByRole('button', { name: 'Save & Enable Bot' }),
  ).toBeVisible({ timeout: 60_000 });

  const botsResponse = await request.get(`${api}/api/v1/platform/bots`, {
    headers,
  });
  expect(botsResponse.ok()).toBeTruthy();
  const bots = (await botsResponse.json()).data.bots as Array<{
    uuid: string;
    adapter: string;
    enable: boolean;
    event_bindings: Array<{ event_pattern: string; target_uuid: string }>;
  }>;
  const bot = bots.find((item) => item.adapter === adapterName);
  expect(
    bot,
    `wizard Bot for adapter ${adapterName} was not created`,
  ).toBeTruthy();
  const binding = bot!.event_bindings.find(
    (item) => item.event_pattern === 'message.received',
  );
  expect(binding?.target_uuid).toBeTruthy();
  const pipelineId = binding!.target_uuid;

  // The offline stack has no Space model catalog. Seed the Local Agent model
  // the same way a configured deployment would have it, then let the wizard
  // save through its real update path.
  const pipelineResponse = await request.get(
    `${api}/api/v1/pipelines/${pipelineId}`,
    { headers },
  );
  expect(pipelineResponse.ok()).toBeTruthy();
  const pipeline = (await pipelineResponse.json()).data.pipeline;
  const config = pipeline.config as Record<string, unknown>;
  const ai = (config.ai ?? {}) as Record<string, unknown>;
  const runnerConfig = (ai.runner_config ?? {}) as Record<string, unknown>;
  const updated = {
    ...config,
    ai: {
      ...ai,
      runner_config: {
        ...runnerConfig,
        [LOCAL_AGENT_RUNNER_ID]: {
          ...((runnerConfig[LOCAL_AGENT_RUNNER_ID] ?? {}) as Record<
            string,
            unknown
          >),
          model: { primary: 'wizard-e2e-model', fallbacks: [] },
        },
      },
    },
  };
  const seeded = await request.put(`${api}/api/v1/pipelines/${pipelineId}`, {
    headers,
    data: { config: updated },
  });
  expect(seeded.ok()).toBeTruthy();
  expect((await seeded.json()).code).toBe(0);

  const saveResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/platform/bots/${bot!.uuid}`) &&
      response.request().method() === 'PUT',
  );
  await page.getByRole('button', { name: 'Save & Enable Bot' }).click();
  expect((await (await saveResponse).json()).code).toBe(0);
  await expect(
    page.getByRole('button', { name: 'Re-save Configuration' }),
  ).toBeVisible({ timeout: 60_000 });

  const savedBotResponse = await request.get(
    `${api}/api/v1/platform/bots/${bot!.uuid}`,
    { headers },
  );
  const savedBot = (await savedBotResponse.json()).data.bot;
  expect(savedBot.enable).toBe(true);
  expect(savedBot.adapter).toBe(adapterName);

  const savedPipelineResponse = await request.get(
    `${api}/api/v1/pipelines/${pipelineId}`,
    { headers },
  );
  const savedPipeline = (await savedPipelineResponse.json()).data.pipeline;
  expect(savedPipeline.config.ai.runner.id).toBe(LOCAL_AGENT_RUNNER_ID);
  expect(
    savedPipeline.config.ai.runner_config[LOCAL_AGENT_RUNNER_ID].model.primary,
  ).toBe('wizard-e2e-model');
});
