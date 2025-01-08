import motor.motor_asyncio

from commons.config import Config as config


class MongoDB:
    def __init__(self, db):
        try:
            mongo_uri = (
                f"mongodb://{config.MONGODB_USER}:{config.MONGODB_PASS}@{config.MONGODB_HOST}:{config.MONGODB_PORT}/"
            )
            self.client = motor.motor_asyncio.AsyncIOMotorClient(mongo_uri)
            self.db = self.client[db]

        except Exception as e:
            print(f"Error al conectar a MongoDB: {e}")
            raise e

    async def insert_document(self, document, collection, ttl=False, upsert=False, query={}):
        try:
            self.collection = self.db[collection]
            if upsert:
                result = await self.collection.update_one(query, {"$set": document}, upsert=True)
                inserted_document = await self.collection.find_one({"_id": result.upserted_id})
                return inserted_document
            result = await self.collection.insert_one(document)
            if ttl:
                await self.collection.create_index("date_expire", expireAfterSeconds=0)
            inserted_document = await self.collection.find_one({"_id": result.inserted_id})
            return inserted_document

        except Exception as e:
            print(f"Error al insertar documento: {e}")
            raise e

    async def find_document(self, query, collection, **params):
        self.collection = self.db[collection]
        document = await self.collection.find_one(query, **params)
        return document

    async def find_documents(self, query, collection, **params):
        self.collection = self.db[collection]
        documents = self.collection.find(query, **params)
        return [{**doc, "_id": str(doc.get("_id"))} async for doc in documents]

    async def update_document(self, collection, query, update, **params):
        self.collection = self.db[collection]
        result = await self.collection.update_one(query, update, **params)
        document = await self.find_document(query=query, collection=collection)
        return document

    async def delete_document(self, collection, query):
        self.collection = self.db[collection]
        result = await self.collection.delete_one(query)
        return result.deleted_count

    async def count_documents(self, collection, query):
        self.collection = self.db[collection]
        count = await self.collection.count_documents(query)
        return count

    async def close_connection(self):
        self.client.close()

    async def delete_all_documents(self, collection: str):
        try:
            self.collection = self.db[collection]
            result = await self.collection.delete_many({})
            return result.deleted_count
        except Exception as e:
            print(f"Error al borrar documentos: {e}")
            raise e
