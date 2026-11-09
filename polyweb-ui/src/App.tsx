import { Route, Routes } from "react-router"
import { AppProviders } from "@/app/AppProviders"
import { DashboardShell } from "@/app/DashboardShell"
import { ProtectedWorkspace } from "@/app/ProtectedWorkspace"
import { LOGIN_PATH, REGISTER_PATH } from "@/app/routes"
import { LoginPage } from "@/features/auth/ui/LoginPage"
import { RegisterPage } from "@/features/auth/ui/RegisterPage"

/**
 * Public route composition. The two account screens stay outside the protected
 * business providers, so an anonymous visitor never mounts a control read. Every
 * other path passes the session gate in `ProtectedWorkspace`.
 */
function App() {
  return (
    <AppProviders>
      <Routes>
        <Route path={LOGIN_PATH} element={<LoginPage />} />
        <Route path={REGISTER_PATH} element={<RegisterPage />} />
        <Route
          path="*"
          element={
            <ProtectedWorkspace>
              <DashboardShell />
            </ProtectedWorkspace>
          }
        />
      </Routes>
    </AppProviders>
  )
}

export default App
