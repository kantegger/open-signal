import { FrontPage } from "../components/front-page";
import { fetchCurrentFrontPage } from "../lib/api";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  let initialData = null;
  try {
    initialData = (await fetchCurrentFrontPage()).data;
  } catch {
    // The client owns retry and preserves the last good in-memory snapshot.
  }
  return <FrontPage initialData={initialData} />;
}
