import { Cabecalho } from './components/Cabecalho'
import { PaginaUpload } from './pages/PaginaUpload'
import estilos from './App.module.css'

function App() {
  return (
    <>
      <Cabecalho />
      <main className={estilos.conteudo}>
        <PaginaUpload />
      </main>
    </>
  )
}

export default App
