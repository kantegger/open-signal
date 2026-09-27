import { Container, getContainer } from "@cloudflare/containers";

// Stable Durable Object identity retained across cadence changes.
const INSTANCE_NAME = "hourly-production";

export class OpenSignalBatch extends Container<Env> {
  // A healthy one-shot exits as soon as the Python batch completes. This is a
  // safety ceiling for a hung batch, not an always-on idle duration.
  sleepAfter = "55m";

  async launch(scheduledAt: string): Promise<LaunchResult> {
    const state = await this.getState();
    if (["running", "healthy", "stopping"].includes(state.status)) {
      return { status: "overlap_skipped", scheduledAt, containerState: state.status };
    }

    await this.start({
      entrypoint: ["python", "-m", "open_signal_worker", "--mode", "once"],
      enableInternet: true,
      envVars: {
        OPEN_SIGNAL_SCHEDULED_AT: scheduledAt,
        OPEN_SIGNAL_DATABASE_URL: this.env.OPEN_SIGNAL_DATABASE_URL,
        DEEPSEEK_API_KEY: this.env.DEEPSEEK_API_KEY,
        OPEN_SIGNAL_R2_ENDPOINT_URL: this.env.OPEN_SIGNAL_R2_ENDPOINT_URL,
        OPEN_SIGNAL_R2_ACCESS_KEY_ID: this.env.OPEN_SIGNAL_R2_ACCESS_KEY_ID,
        OPEN_SIGNAL_R2_SECRET_ACCESS_KEY: this.env.OPEN_SIGNAL_R2_SECRET_ACCESS_KEY,
        OPEN_SIGNAL_R2_PUBLIC_BUCKET: this.env.OPEN_SIGNAL_R2_PUBLIC_BUCKET,
        OPEN_SIGNAL_REVALIDATE_URL: this.env.OPEN_SIGNAL_REVALIDATE_URL,
        OPEN_SIGNAL_REVALIDATE_TOKEN: this.env.OPEN_SIGNAL_REVALIDATE_TOKEN,
      },
    });
    return { status: "started", scheduledAt, containerState: state.status };
  }
}

export default {
  async fetch(): Promise<Response> {
    return Response.json({ service: "open-signal-scheduler", cadence: "every_3_days" });
  },

  async scheduled(controller, env): Promise<void> {
    const scheduledAt = new Date(controller.scheduledTime).toISOString();
    try {
      const container = getContainer(env.OPEN_SIGNAL_BATCH, INSTANCE_NAME);
      const result = await container.launch(scheduledAt);
      console.log(JSON.stringify({ event: "open_signal_batch_launch", ...result }));
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "open_signal_batch_launch_failed",
          scheduledAt,
          error: error instanceof Error ? error.message : String(error),
        }),
      );
      throw error;
    }
  },
} satisfies ExportedHandler<Env>;

interface LaunchResult {
  status: "started" | "overlap_skipped";
  scheduledAt: string;
  containerState: string;
}
