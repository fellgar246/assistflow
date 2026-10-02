import { AgentConsole } from "@/components/agent/console";

export default async function StaffConversationPage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  return <AgentConsole conversationId={conversationId} />;
}
