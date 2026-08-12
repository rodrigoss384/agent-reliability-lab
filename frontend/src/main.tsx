import React from "react";
import { createRoot } from "react-dom/client";
import ChatScreen from "./features/rag-pii-chat/ChatScreen";
import "./index.css";

const container = document.getElementById("root");
if (container) {
  const root = createRoot(container);
  root.render(
    <React.StrictMode>
      <ChatScreen />
    </React.StrictMode>
  );
}
