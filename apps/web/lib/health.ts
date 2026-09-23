import { z } from "zod";

export const healthStatusSchema = z.object({
  status: z.literal("healthy"),
});

export type HealthStatus = z.infer<typeof healthStatusSchema>;

export function parseHealthStatus(payload: unknown): HealthStatus {
  return healthStatusSchema.parse(payload);
}
