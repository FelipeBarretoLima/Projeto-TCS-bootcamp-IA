import estilos from './Marca.module.css'

export function Marca() {
  return (
    <span className={estilos.marca} aria-label="TAS – Transactions Assistancy Service">
      <span className={estilos.sigla} aria-hidden="true">
        tas
      </span>
      <span className={estilos.nome} aria-hidden="true">
        <span className={estilos.linha1}>Transactions</span>
        <span>Assistancy</span>
        <span>Service</span>
      </span>
    </span>
  )
}
