import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom"
import { ChatPage } from "@/pages/ChatPage"
import { DashboardPage } from "@/pages/DashboardPage"

export default function App() {
  return (
    <BrowserRouter>
      <div className="h-screen flex flex-col bg-background text-foreground">
        <nav className="border-b px-6 py-3 flex gap-6 items-center shrink-0">
          <span className="text-sm font-semibold mr-4">Lio</span>
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `text-sm ${isActive ? "font-medium" : "text-muted-foreground hover:text-foreground"}`
            }
          >
            Chat
          </NavLink>
          <NavLink
            to="/dashboard"
            className={({ isActive }) =>
              `text-sm ${isActive ? "font-medium" : "text-muted-foreground hover:text-foreground"}`
            }
          >
            Dashboard
          </NavLink>
        </nav>
        <div className="flex-1 min-h-0 flex">
          <Routes>
            <Route path="/" element={<ChatPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}
