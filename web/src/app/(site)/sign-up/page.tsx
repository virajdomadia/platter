import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthForm } from "@/components/site/AuthForm";

export const metadata: Metadata = { title: "Create an account", alternates: { canonical: "/sign-up" } };

export default function Page() {
  return (
    <Suspense>
      <AuthForm mode="sign-up" />
    </Suspense>
  );
}
