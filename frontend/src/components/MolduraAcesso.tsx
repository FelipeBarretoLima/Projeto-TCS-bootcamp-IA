// Moldura das telas de fora do app (login e redefinir senha): frase ao lado, caixa ao centro.

import { Moon, Sun } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTema } from '../hooks/useTema'
import estilos from '../pages/PaginaLogin.module.css'
import { Marca } from './Marca'

type Props = { titulo: string; subtitulo: string; children: ReactNode }

export function MolduraAcesso({ titulo, subtitulo, children }: Props) {
  const { tema, alterna } = useTema()
  return (
    <div className={estilos.tela}>
      <aside className={estilos.lateral} aria-hidden="true">
        <div className={estilos.frase}>
          <p className={estilos.chamada}>
            Suas finanças,
            <br />
            em conversa.
          </p>
          <p className={estilos.apoio}>
            Importe extratos em PDF e pergunte ao assistente o que quiser sobre seus gastos.
          </p>
        </div>
      </aside>

      <main className={estilos.principal}>
        <button
          type="button"
          className={estilos.tema}
          onClick={alterna}
          aria-label={`Mudar para o tema ${tema === 'claro' ? 'escuro' : 'claro'}`}
        >
          {tema === 'claro' ? <Moon size={20} /> : <Sun size={20} />}
        </button>

        <div className={estilos.caixa}>
          <Marca />
          <h1>{titulo}</h1>
          <p className={estilos.subtitulo}>{subtitulo}</p>
          {children}
        </div>
      </main>
    </div>
  )
}
