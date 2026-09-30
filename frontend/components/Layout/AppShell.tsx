"use client";

import { ReactNode, useState } from "react";
import NavBar from "@/components/Layout/NavBar";
import AdminView from "@/components/Layout/AdminView";
import ChatbotPanel from "@/components/ChatbotPanel";
import LoginModal from "@/components/Auth/LoginModal";
import type { DemoUser } from "@/lib/auth";

type AppShellProps = {
  children: ReactNode;
};

export default function AppShell({ children }: AppShellProps) {
  const [isChatbotOpen, setIsChatbotOpen] = useState(false);
  const [isAdminOpen, setIsAdminOpen] = useState(false);
  const [isLoginOpen, setIsLoginOpen] = useState(false);
  // The signed-in shopper the Personal assistant will later personalise for.
  const [currentUser, setCurrentUser] = useState<DemoUser | null>(null);

  return (
    <>
      <NavBar
        isChatbotOpen={isChatbotOpen}
        onToggleChatbot={() => setIsChatbotOpen((prevValue) => !prevValue)}
        isAdminView={isAdminOpen}
        onOpenAdmin={() => {
          setIsChatbotOpen(false);
          setIsAdminOpen(true);
        }}
        onReturnFromAdmin={() => setIsAdminOpen(false)}
        currentUser={currentUser}
        onOpenLogin={() => setIsLoginOpen(true)}
        onLogout={() => setCurrentUser(null)}
      />
      <LoginModal
        isOpen={isLoginOpen}
        onClose={() => setIsLoginOpen(false)}
        onLoggedIn={setCurrentUser}
      />
      {isAdminOpen ? null : (
        <ChatbotPanel
          isOpen={isChatbotOpen}
          onClose={() => setIsChatbotOpen(false)}
          currentUser={currentUser}
        />
      )}
      {isAdminOpen ? <AdminView /> : null}
      {/* Kept mounted (not unmounted) so the shopper's page, scroll position, and
          filters survive the round trip through the admin view. */}
      <div className={`flex-1 flex flex-col pt-16 ${isAdminOpen ? "hidden" : ""}`}>
        {children}
      </div>
    </>
  );
}