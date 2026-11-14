import { loadInbox } from "@/lib/data";
import Inbox from "@/components/Inbox";

// Built once per deploy from the committed seed; the nightly data commit redeploys it.
export const dynamic = "force-static";

export default function Page() {
  return <Inbox data={loadInbox()} />;
}
