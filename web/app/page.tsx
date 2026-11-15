import { loadInbox } from "@/lib/data";
import NewsFeed from "@/components/news/NewsFeed";

// Built once per deploy from the committed seed; a data commit redeploys it.
export const dynamic = "force-static";

export default function Page() {
  return <NewsFeed data={loadInbox()} />;
}
