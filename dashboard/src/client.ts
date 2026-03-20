import { createConnectTransport } from "@connectrpc/connect-web";
import { createClient } from "@connectrpc/connect";
import { OrchestratorService } from "./gen/omega/v1/omega_service_pb";

const baseUrl = import.meta.env.VITE_API_URL ?? "";

export const transport = createConnectTransport({ baseUrl });
export const client = createClient(OrchestratorService, transport);
