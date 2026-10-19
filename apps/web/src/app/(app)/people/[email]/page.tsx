import { entityMetadata, entityPage } from "@/components/entity-route";

export const generateMetadata = entityMetadata("person", "Person", "email");

export default entityPage("person", "email");
