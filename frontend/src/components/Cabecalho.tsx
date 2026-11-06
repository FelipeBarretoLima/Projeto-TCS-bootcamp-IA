import { Moon, Sun } from 'lucide-react'
import { useTema } from '../hooks/useTema'
import { Marca } from './Marca'
import { StatusApi } from './StatusApi'
import estilos from './Cabecalho.module.css'

export function Cabecalho() {
  const { tema, alterna } = useTema()
  const proximo = tema === 'claro' ? 'escuro' : 'claro'

  return (
    <header className={estilos.cabecalho}>
      <div className={estilos.conteudo}>
        <Marca />
        <nav className={estilos.navegacao} aria-label="Principal">
          <a className={estilos.ativo} href="/" aria-current="page">
            Importar extrato
          </a>
        </nav>
        <div className={estilos.acoes}>
          <StatusApi />
          <button
            type="button"
            className={estilos.icone}
            onClick={alterna}
            aria-label={`Mudar para o tema ${proximo}`}
            title={`Tema ${proximo}`}
          >
            {tema === 'claro' ? <Moon size={20} /> : <Sun size={20} />}
          </button>
        </div>
      </div>
    </header>
  )
}
