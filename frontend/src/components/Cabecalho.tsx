import { LogOut, Moon, Sun } from 'lucide-react'
import { NavLink } from 'react-router'
import { useAutenticacao } from '../contexto/contextoAuth'
import { useTema } from '../hooks/useTema'
import { Marca } from './Marca'
import { StatusApi } from './StatusApi'
import estilos from './Cabecalho.module.css'

const classeLink = ({ isActive }: { isActive: boolean }) => (isActive ? estilos.ativo : undefined)

export function Cabecalho() {
  const { tema, alterna } = useTema()
  const { sai } = useAutenticacao()
  const proximo = tema === 'claro' ? 'escuro' : 'claro'

  return (
    <header className={estilos.cabecalho}>
      <div className={estilos.conteudo}>
        <Marca />
        <nav className={estilos.navegacao} aria-label="Principal">
          <NavLink to="/importar" className={classeLink}>
            Importar extrato
          </NavLink>
          <NavLink to="/extrato" className={classeLink}>
            Extrato
          </NavLink>
          <NavLink to="/dashboard" className={classeLink}>
            Dashboard
          </NavLink>
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
          <button type="button" className={estilos.icone} onClick={() => void sai()} aria-label="Sair" title="Sair">
            <LogOut size={20} />
          </button>
        </div>
      </div>
    </header>
  )
}
