i have used this sparql query as below

PREFIX : <http://www.ontotext.com/graphdb/similarity/>
PREFIX inst: <http://www.ontotext.com/graphdb/similarity/instance/>

SELECT ?entity (MAX(?score) AS ?bestScore)
WHERE {
    ?search a inst:bldg_index ;
            :searchTerm "Air quality level in room 5.26" ;
            :documentResult ?result .
    ?result :value ?entity ;
            :score ?score .
}
GROUP BY ?entity
ORDER BY DESC(?bestScore)
LIMIT 20
