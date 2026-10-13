// Un fichier lu tel quel par Vite (`import texte from "…?raw"`) : les tests du
// monde lisent ainsi la spécification et les mondes du noyau.
declare module "*?raw" {
  const text: string;
  export default text;
}
