import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { Cabecalho } from './components/Cabecalho'
import { ProvedorAutenticacao } from './contexto/Autenticacao'
import { useAutenticacao } from './contexto/contextoAuth'
import { PaginaDashboard } from './pages/PaginaDashboard'
import { PaginaExtrato } from './pages/PaginaExtrato'
import { PaginaLogin } from './pages/PaginaLogin'
import { PaginaUpload } from './pages/PaginaUpload'
import estilos from './App.module.css'

/** Páginas que exigem login: sem sessão, vai para /login (depois de entrar, abre Importar extrato). */
function Protegida({ children }: { children: ReactNode }) {
  const { estado } = useAutenticacao()
  if (estado.fase === 'carregando') return <p className={estilos.carregando}>Carregando…</p>
  if (estado.fase === 'pronto' && estado.sessao) {
    return (
      <>
        <Cabecalho />
        <main className={estilos.conteudo}>{children}</main>
      </>
    )
  }
  return <Navigate to="/login" replace />
}

function Rotas() {
  return (
    <Routes>
      <Route path="/login" element={<PaginaLogin />} />
      <Route path="/importar" element={<Protegida><PaginaUpload /></Protegida>} />
      <Route path="/extrato" element={<Protegida><PaginaExtrato /></Protegida>} />
      <Route path="/dashboard" element={<Protegida><PaginaDashboard /></Protegida>} />
      <Route path="*" element={<Navigate to="/importar" replace />} />
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
