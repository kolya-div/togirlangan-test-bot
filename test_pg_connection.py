"""
Test PostgreSQL connection
"""
import asyncio
import asyncpg

async def test_connection():
    try:
        conn = await asyncpg.connect(
            host='localhost',
            port=5432,
            user='postgres',
            password='123',
            database='postgres'
        )
        version = await conn.fetchval('SELECT version()')
        current_db = await conn.fetchval('SELECT current_database()')
        current_user = await conn.fetchval('SELECT current_user')
        
        print(f"PostgreSQL Version: {version}")
        print(f"Current Database: {current_db}")
        print(f"Current User: {current_user}")
        
        await conn.close()
        return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False

if __name__ == '__main__':
    result = asyncio.run(test_connection())
    print(f"\nConnection Test: {'PASS' if result else 'FAIL'}")