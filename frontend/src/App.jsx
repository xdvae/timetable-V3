import { RouterProvider } from "react-router";

import { Providers } from "./app/providers.jsx";
import { router } from "./app/router.jsx";

/** Application root: global providers + route tree. Pages live in src/pages/. */
export default function App() {
  return (
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  );
}
