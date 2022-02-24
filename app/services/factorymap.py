from app.core.database import FactoryMap


async def get_all_factory_maps():
    return await FactoryMap.objects.all()


async def get_factory_map_by_id(factory_map_id: int):
    return await FactoryMap.objects.filter(id=factory_map_id).get_or_none()


async def get_factory_map_by_name(factory_map_name: int):
    return await FactoryMap.objects.filter(name=factory_map_name).get_or_none()

