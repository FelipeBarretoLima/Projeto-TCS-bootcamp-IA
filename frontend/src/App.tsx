import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router'
import { Cabecalho } from './components/Cabecalho'
import { ProvedorAutenticacao } from './contexto/Autenticacao'
import { useAutenticacao } from './contexto/contextoAuth'
import { PaginaDashboard } from './pages/PaginaDashboard'
import { PaginaLogin } from './pages/PaginaLogin'
import { PaginaUpload } from './pages/PaginaUpload'
import estilos from './App.module.css'

/** Páginas que exigem login: sem sessão, vai para /login (e volta depois de entrar). */
function Protegida({ children }: { children: ReactNode }) {
  const { estado } = useAutenticacao()
  const local = useLocation()
  if (estado.fase === 'carregando') return <p className={estilos.carregando}>Carregando…</p>
  if (estado.fase === 'pronto' && estado.sessao) {
    return (
      <>
        <Cabecalho />
        <main className={estilos.conteudo}>{children}</main>
      </>
    )
  }
  return <Navigate to="/login" replace state={{ de: local.pathname }} />
}

function Rotas() {
  return (
    <Routes>
      <Route path="/login" element={<PaginaLogin />} />
      <Route path="/importar" element={<Protegida><PaginaUpload /></Protegida>} />
      <Route path="/dashboard" element={<Protegida><PaginaDashboard /></Protegida>} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ProvedorAutenticacao>
        <Rotas />
      </ProvedorAutenticacao>
    </BrowserRouter>
  )
}
