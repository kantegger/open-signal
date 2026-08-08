import { FrontPage } from "../components/front-page";
import { fetchCurrentFrontPageServer } from "../lib/server-api";

export const revalidate = 86_400;

export default async function HomePage() {
  let initialData = null;
  try {
    initialData = await fetchCurrentFrontPageServer();
  } catch {
    // The client owns retry and preserves the last good in-memory snapshot.
  }
  return <FrontPage initialData={initialData} />;
}
