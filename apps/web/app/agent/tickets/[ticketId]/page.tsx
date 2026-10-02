import { TicketView } from "@/components/agent/ticket-view";

export default async function TicketPage({
  params,
}: {
  params: Promise<{ ticketId: string }>;
}) {
  const { ticketId } = await params;
  return <TicketView ticketId={ticketId} />;
}
