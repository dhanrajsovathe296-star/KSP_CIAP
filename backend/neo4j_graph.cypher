// =====================================================================
// KSP CIAP — Neo4j graph model
// Mirrors suspect/location/incident relationships from Postgres for
// fast traversal queries ("who was near whom, when").
// =====================================================================

// --- Constraints -------------------------------------------------
CREATE CONSTRAINT suspect_id IF NOT EXISTS FOR (s:Suspect) REQUIRE s.suspect_id IS UNIQUE;
CREATE CONSTRAINT location_id IF NOT EXISTS FOR (l:Location) REQUIRE l.location_id IS UNIQUE;
CREATE CONSTRAINT incident_id IF NOT EXISTS FOR (i:Incident) REQUIRE i.incident_id IS UNIQUE;

// --- Node examples -------------------------------------------------
// (:Suspect {suspect_id, full_name, risk_flag})
// (:Location {location_id, name, district})
// (:Incident {incident_id, fir_number, occurred_at, crime_type})
// (:MO {name})   -- modus operandi as its own node enables MO-clustering

// --- Relationship examples ------------------------------------------
// (Suspect)-[:INVOLVED_IN {role}]->(Incident)
// (Incident)-[:OCCURRED_AT]->(Location)
// (Incident)-[:USED_MO]->(MO)
// (Suspect)-[:ASSOCIATE_OF {weight, first_seen}]->(Suspect)   -- derived edge

// ---------------------------------------------------------------------
// Load example (from a staged CSV produced by the Pandas ingestion job)
// ---------------------------------------------------------------------
// LOAD CSV WITH HEADERS FROM 'file:///incidents_staged.csv' AS row
// MERGE (s:Suspect {suspect_id: row.suspect_id})
//   ON CREATE SET s.full_name = row.suspect_name, s.risk_flag = false
// MERGE (l:Location {location_id: row.location_id})
//   ON CREATE SET l.name = row.location_name, l.district = row.district
// MERGE (i:Incident {incident_id: row.incident_id})
//   ON CREATE SET i.fir_number = row.fir_number,
//                 i.occurred_at = datetime(row.occurred_at),
//                 i.crime_type = row.crime_type
// MERGE (s)-[:INVOLVED_IN {role: row.role}]->(i)
// MERGE (i)-[:OCCURRED_AT]->(l);

// ---------------------------------------------------------------------
// Core link-analysis query: "Find all suspects who have been at the
// same location as Suspect X within the last 30 days"
// ---------------------------------------------------------------------
// MATCH (target:Suspect {suspect_id: $suspectId})-[:INVOLVED_IN]->(:Incident)-[:OCCURRED_AT]->(loc:Location)
// MATCH (other:Suspect)-[:INVOLVED_IN]->(i2:Incident)-[:OCCURRED_AT]->(loc)
// WHERE other.suspect_id <> target.suspect_id
//   AND i2.occurred_at >= datetime() - duration({days: 30})
// RETURN DISTINCT other.full_name, loc.name, i2.occurred_at
// ORDER BY i2.occurred_at DESC;

// ---------------------------------------------------------------------
// Derive an ASSOCIATE_OF edge weighted by shared-location frequency
// (run periodically, e.g. nightly, to keep the graph fresh)
// ---------------------------------------------------------------------
// MATCH (a:Suspect)-[:INVOLVED_IN]->(:Incident)-[:OCCURRED_AT]->(loc:Location)
//       <-[:OCCURRED_AT]-(:Incident)<-[:INVOLVED_IN]-(b:Suspect)
// WHERE a.suspect_id < b.suspect_id
// WITH a, b, count(DISTINCT loc) AS shared_locations
// WHERE shared_locations >= 2
// MERGE (a)-[r:ASSOCIATE_OF]-(b)
// SET r.weight = shared_locations, r.updated_at = datetime();

// ---------------------------------------------------------------------
// MO clustering: suspects who repeat a specific modus operandi
// ---------------------------------------------------------------------
// MATCH (s:Suspect)-[:INVOLVED_IN]->(i:Incident)-[:USED_MO]->(mo:MO {name: $moName})
// WITH s, count(i) AS occurrences
// WHERE occurrences >= 2
// RETURN s.full_name, occurrences
// ORDER BY occurrences DESC;
